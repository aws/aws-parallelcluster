import boto3
from botocore.exceptions import ClientError
import argparse
import json
import pkg_resources

UNSUPPORTED_REGIONS =set(['ap-northeast-3', 'eu-west-3'])

def get_all_aws_regions():
    ec2 = boto3.client('ec2')
    return set(sorted(r.get('RegionName') for r in ec2.describe_regions().get('Regions'))) - UNSUPPORTED_REGIONS

def upload_to_s3(args, region):
    s3_client = boto3.resource('s3', region_name=region)

    if args.bucket:
        buckets = args.bucket.split(',')
    else:
        buckets = ['%s-aws-parallelcluster' % region]
    key_path = 'templates/'
    template_paths = 'cloudformation/'

    for t in args.templates:
        template_name = '%s%s.cfn.json' % (template_paths, t)
        key = key_path + '%s-%s.cfn.json' % (t, args.version)
        data = open(template_name, 'rb')
        for bucket in buckets:
            if args.dryrun:
                key = key_path + '%s-%s.cfn.json' % (t, args.version)
                print("Skipping upload %s to s3://%s/%s" % (template_name, bucket, key))
                continue
            if not args.override:
                try:
                    s3 = boto3.client('s3', region_name=region)
                    s3.head_object(Bucket=bucket, Key=key)
                    print('%s already exist in bucket %s, skipping upload...' % (key, bucket))
                    continue
                except ClientError:
                    pass
            try:
                object = s3_client.Object(bucket, key)
                response = object.put(Body=data, ACL='public-read',)
                if response.get('ResponseMetadata').get('HTTPStatusCode') == 200:
                    print("Successfully uploaded %s to s3://%s/%s" % (template_name, bucket, key))
            except ClientError as e:
                if args.createifnobucket and e.response['Error']['Code'] == 'NoSuchBucket':
                    print('No bucket, creating now: ')
                    s3_client.create_bucket(Bucket=bucket,
                                                  CreateBucketConfiguration={'LocationConstraint': region})
                    s3_client.BucketVersioning(bucket).enable()
                    print("Created %s bucket. Bucket versioning is enabled, "
                          "please enable bucket logging manually." % bucket)
                    b = s3_client.Bucket(bucket)
                    res = b.put_object(Body=data, ACL='public-read', Key=key)
                    print(res)
                else:
                    print("Couldn't upload %s to bucket s3://%s/%s" % (template_name, bucket, key))
                    raise e
                pass

def main(args):
    # For all regions
    for region in args.regions:
        upload_to_s3(args, region)


if __name__ == '__main__':
    # parse inputs
    parser = argparse.ArgumentParser(description='Upload extra templates under /cloudformation')
    parser.add_argument('--regions', type=str, help='Valid Regions, can include "all", or comma separated list of regions', required=True)
    parser.add_argument('--templates', type=str,
                        help='Template filenames, leave out \'.cfn.json\', comma separated list', required=True)
    parser.add_argument('--bucket', type=str, help='Buckets to upload to, defaults to [region]-aws-parallelcluster, comma separated list', required=False)
    parser.add_argument('--dryrun', type=bool, help="Doesn't push anything to S3, just outputs", required=False)
    parser.add_argument('--override', type=bool, help="If override is false, the file will not be pushed if it already exists in the bucket", required=False)
    parser.add_argument('--createifnobucket', type=bool, help="Create S3 bucket if it does not exist", required=False)
    args = parser.parse_args()
    args.version = pkg_resources.get_distribution("aws-parallelcluster").version

    if args.regions == 'all':
        args.regions = get_all_aws_regions()
    else:
        args.regions = args.regions.split(',')

    args.templates = args.templates.split(',')

    main(args)