#!/usr/bin/env python
from distutils import dir_util as dirutil
from shutil import copy
import argparse
import configparser
import os
import subprocess
import sys
import tempfile

from botocore.exceptions import ClientError
from jinja2 import Template
import boto3

def _check_docker():
    # check that docker is installed
    if subprocess.call(['docker', '-v']) != 0:
        print('Docker is not installed properly')
        sys.exit(1)

def _resolve_s3(bucket_name, region):
    # create s3 bucket if it does not exist
    s3 = boto3.resource('s3')
    if s3.Bucket(name=bucket_name) in s3.buckets.all():
        # if bucket already exists, check loca
        location = s3.meta.client.get_bucket_location(
            Bucket=bucket_name).get('LocationConstraint')
        location = 'us-east-1' if location == None else location
        if location != region:
            print('Bucket {} is in {}, should be in {}'.format(
                bucket_name, location, region))
            sys.exit(1)
    else:
        # if 'us-east-1' CreateBucketConfiguration must be omitted
        if region == 'us-east-1':
            bucket = s3.create_bucket(Bucket=bucket_name)
        else:
            bucket = s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={
                    'LocationConstraint': region
                }
            )
        bucket.wait_until_exists()

def _copy_source(script_path):
    # create temporary directory
    tempdir = tempfile.mkdtemp(dir='/tmp')

    # copy source code and cfn template to tempdir
    dirutil.copy_tree(os.path.join(script_path, 'src'), tempdir)
    dirutil.copy_tree(os.path.join(script_path, 'templates'), tempdir)

    print('Created temporary directory: {}'.format(tempdir))
    return tempdir

def _edit_key_param(tempdir, config_file, key_name):
    # get configuration file
    config_path = os.path.realpath(config_file)
    config = configparser.ConfigParser()
    config.readfp(open(config_path))

    # set key_name of config
    template = config.get('global', 'cluster_template')
    config.set('cluster {}'.format(template), 'key_name', key_name)

    # output with new key_name to a copy
    os.mkdir(os.path.join(tempdir, 'config'))
    new_config = open(os.path.join(tempdir, 'config', 'cfncluster.config'), 'w+')
    config.write(new_config)
    new_config.close()
    print('Copied cfncluster config with key_name={}'.format(key_name))

    return config

def _package_jobs(tempdir, jobs_config, config, script_dir):
    # setup jobs temp folder and copy jobs config
    try:
        os.mkdir(os.path.join(tempdir, 'jobs'))
        config_path = os.path.realpath(jobs_config)
        copy(config_path, os.path.join(tempdir, 'jobs.config'))
        config.readfp(open(config_path))
    except IOError:
        msg = 'Must specify a real file for the jobs config.\n' \
            'A working example can be found at {}'
        loc = os.path.join(script_dir, 'jobs', 'jobs.config')
        print(msg.format(loc))
        sys.exit(1)

    # package user specified jobs
    job_sections = filter(lambda x: 'job ' in x, config.sections())
    for section in job_sections:
        job_name = section[4:]
        new_path = os.path.join(tempdir, 'jobs', job_name)
        os.mkdir(new_path)
        is_s3 = 's3_uri' in config.options(section)
        is_local = 'local_path' in config.options(section)
        if is_s3 and is_local:
            print('Must specify s3_uri or local_path, not both')
            sys.exit(1)
        elif is_s3:
            # if s3 use aws s3 short commands
            uri = config.get(section, 's3_uri')
            print(subprocess.check_output(
                ['aws', 's3', 'cp', uri, new_path]
            ))
        elif is_local:
            # if local path copy file/directory
            path = config.get(section, 'local_path')
            config_folder = os.path.dirname(config_path)
            job_path = os.path.join(config_folder, path)
            if os.path.isdir(job_path):
                dirutil.copy_tree(job_path, new_path)
            else:
                copy(job_path, new_path)
        else:
            print('Need to specify s3_uri or local_path in {} section'.format(section))
            sys.exit(1)

def _generate_template(script_path, tempdir, config):
    # dynamically generate cfn template based on jobs config
    template_txt = open(os.path.join(tempdir, 'template.yaml'), 'r').read()
    cfn_template = Template(template_txt)

    # handle sequential and parallel job execution types
    if 'sequential' in config.options('order'):
        job_txt = open(os.path.join(script_path, 'job_sequential.txt'), 'r').read()
        sequential = config.get('order', 'sequential')
        jobs = sequential.split(',')
        jobs = map(lambda x: x.strip(), jobs)
        job_list = []
        for job in jobs:
            sec = 10
            section = 'job {}'.format(job)
            if 'wait_time' in config.options(section):
                sec = int(config.get(section, 'wait_time'))
            if sec <= 0 or sec > 240:
                print('wait_time must be between 1 and 240 seconds inclusive')
                sys.exit(1)
            index = jobs.index(job)
            end = 'Delete_CfnCluster' if index == len(jobs) - 1 else \
                'Pass_Job_{}'.format(jobs[index + 1])
            handler = config.get(section, 'handler')
            job_list.append({
                'name': job, 'sec': sec, 'end': end, 'handler': handler
            })
        sequential_template = Template(job_txt)
        job_def = sequential_template.render(job_list=job_list)
        entry = 'Pass_Job_{}'.format(jobs[0])
    elif 'parallel' in config.options('order'):
        job_txt = open(os.path.join(script_path, 'job_parallel.txt'), 'r').read()
        parallel = config.get('order', 'parallel')
        jobs = parallel.split(',')
        jobs = map(lambda x: x.strip(), jobs)
        job_list = []
        for job in jobs:
            sec = 10
            section = 'job {}'.format(job)
            if 'wait_time' in config.options(section):
                sec = int(config.get(section, 'wait_time'))
            if sec <= 0 or sec > 240:
                print('wait_time must be between 1 and 240 seconds inclusive')
                sys.exit(1)
            handler = config.get(section, 'handler')
            job_list.append({'name': job, 'sec': sec, 'handler': handler})
        parallel_template = Template(job_txt)
        job_def = parallel_template.render(job_list=job_list)
        entry = 'Parallel_Job_Execution'
    
    # output dynamically generated template
    new_cfn_txt = cfn_template.render(entry=entry, jobs=job_def)
    open(os.path.join(tempdir, 'template.yaml'), 'w').write(new_cfn_txt)

def _package(config_file, key_name, jobs_config):
    script_path = os.path.dirname(os.path.realpath(__file__))
    tempdir = _copy_source(script_path)
    config = _edit_key_param(tempdir, config_file, key_name)
    _package_jobs(tempdir, jobs_config, config, script_path)
    _generate_template(script_path, tempdir, config)
    return tempdir

def _deeplink_url(region, stack_name):
    # get outputs from cfn to use in url
    try:
        cloudformation = boto3.resource(
            'cloudformation', region_name=region)
        stack = cloudformation.Stack(stack_name)
        stackId = stack.stack_id
        outputs = stack.outputs
        machineArn = filter(
            lambda op: op['OutputKey'] == 'StateMachineArn', outputs
        )[0]['OutputValue']
    except ClientError as e:
        print(e.response.get('Error').get('Message'))
        sys.exit(1)

    # fill and print url
    url_region = '{}.'.format(region) if region != 'us-east-1' else ''
    print('URL to Step Function State Machine:')
    print('https://{}console.aws.amazon.com/states/home?region={}#/' \
        'statemachines/view/{}?registered=true&stackId={}'.format(
        url_region, region, machineArn, stackId))

def deploy(args):
    """Deploys the CloudFormation stack based on args

    Args:
        args: arguments passed in by argparse library
    """
    _check_docker()
    _resolve_s3(args.bucket_name, args.region)
    tempdir = _package(args.config_file, args.key_name, args.jobs_config)

    print('Packaging up all dependencies, this can take a moment...')

    # package and deploy the cloudformation stack
    try:
        path_dir = os.path.dirname(os.path.realpath(__file__))
        path = os.path.join(path_dir, 'package.sh')
        print(subprocess.check_output([path, tempdir, 
            args.bucket_name, args.stack_name, args.region, path_dir]))
    except subprocess.CalledProcessError as e:
        print(e.output)
        sys.exit(1)

    _deeplink_url(args.region, args.stack_name)
