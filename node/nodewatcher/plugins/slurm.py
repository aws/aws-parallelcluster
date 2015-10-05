import subprocess


def getJobs(hostname):
    # Checking for running jobs on the node
    _command = ['/opt/slurm/bin/squeue', '-w', hostname, '-h']
    try:
        output = subprocess.Popen(_command, stdout=subprocess.PIPE).communicate()[0]
    except subprocess.CalledProcessError:
        print ("Failed to run %s\n" % _command)

    if output == "":
        _jobs = False
    else:
        _jobs = True

    return _jobs
