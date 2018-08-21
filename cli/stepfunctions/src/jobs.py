import configparser
import logging
import os
import time
import zipfile

from handlers import EC2_SSH, EC2_SFTP

# set logger and log level
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class JobSchedulingException(Exception):
    pass

commands = {
    'schedule': {
        'sge': '. /opt/sge/default/common/settings.sh; cd {}; qsub {} |& grep \'submitted\' | awk \'{{print $3}}\'',
        'torque': 'cd {}; qsub {} |& awk -F. \'{{$0=$1}}1\'',
        'slurm': 'cd {}; sbatch {} |& awk \'{{print $4}}\''
    },
    'poll': {
        'sge': '. /opt/sge/default/common/settings.sh; qstat | awk \'$1 == {} {{print $5}}\'',
        'torque': 'qstat -c | awk -F. \'$1 == {} {{print $0}}\' | awk \'{{print $5}}\'',
        'slurm': 'scontrol show job {} | grep JobState | awk \'{{print $1}}\' | awk -F= \'{{print $2}}\''
    },
    'job_status': {
        'queued': {
            'sge': 'qw',
            'torque': 'Q',
            'slurm': 'PENDING'
        },
        'running': {
            'sge': 'r',
            'torque': 'R',
            'slurm': 'RUNNING'
        }
    },
    'exit_code': {
        'sge': '. /opt/sge/default/common/settings.sh; qacct -j {} | grep exit_status | awk \'{{print $2}}\'',
        'torque': 'qstat -f {} | grep exit_status | awk \'{{print $3}}\'',
        'slurm': 'scontrol show job {} | grep ExitCode= | awk \'{{print $5}}\' | awk -F= \'{{print $2}}\' | awk -F: \'{{print $1}}\''
    }
}

def run_job(event, context):
    """Runs an example job

    Args:
        event: contains ip for the master node of the cfncluster
    """
    logging.debug('event = {}\ncontext = {}'.format(event, context))

    job_name = event['job_info']['name']
    job_handler = event['job_info']['handler']
    scheduler = event['scheduler']

    workdir = event['workdir']
    master_ip = event['master_ip']
    user_name = event['user_name']
    key_name = event['key_name']

    # package job
    zip_name = '{}.zip'.format(job_name)
    zip_path = os.path.join('/tmp', zip_name)
    zip_file = zipfile.ZipFile(zip_path, 'w')
    for root, dirs, files in os.walk(os.path.join('jobs', job_name)):
        for file in files:
            local_path = os.path.join(root, file)
            remote_path = os.path.join(root[5:], file)
            zip_file.write(local_path, remote_path)
    zip_file.close()

    # upload job via sftp
    with EC2_SFTP(master_ip, user_name, key_name) as sftp_client:
        sftp_client.chdir(workdir)
        sftp_client.put(zip_path, zip_name)

    # schedule job
    with EC2_SSH(master_ip, user_name, key_name) as ssh_client:
        zip_path = os.path.join(workdir, job_name)
        command = 'unzip {}.zip -d {}'.format(zip_path, workdir)
        output = ssh_client.exec_command(command)[1].read().strip()

        command = commands['schedule'][scheduler]
        command = command.format(os.path.join(workdir, job_name), job_handler)
        logging.info(command)
        schedule = ssh_client.exec_command(command)
        job_id = schedule[1].read().strip()
        logging.info(schedule[1])
        logging.info(schedule[1].read())

    # handle errors
    if job_id == '':
        message = 'Job {} failed to schedule'.format(job_name)
        raise JobSchedulingException(message)
    
    event['job_id'] = job_id
    return event

def is_job_done(event, context):
    """Determines whether the job is complete

    Args:
        event: contains job id to check whether complete
    """
    logging.debug('event = {}\ncontext = {}'.format(event, context))

    scheduler = event['scheduler']
    master_ip = event['master_ip']
    user_name = event['user_name']
    key_name = event['key_name']

    # check job status
    with EC2_SSH(master_ip, user_name, key_name) as ssh_client:
        command = commands['poll'][scheduler].format(event['job_id'])
        status = ssh_client.exec_command(command)[1].read().strip()
    
        queued = commands['job_status']['queued'][scheduler]
        running = commands['job_status']['running'][scheduler]

        if status == queued or status == running:
            event['status'] = 'idle'
        else:
            command = commands['exit_code'][scheduler].format(event['job_id'])

            # attempt to wait for job journaling
            t_end = time.time() + 30
            while time.time() < t_end:
                try:
                    code = ssh_client.exec_command(command)[1].read().strip()
                    code = int(code)
                    break
                except ValueError:
                    time.sleep(1)

            event['status'] = 'complete' if code == 0 else 'failed'

    return event
