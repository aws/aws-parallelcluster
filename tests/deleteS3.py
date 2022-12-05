import boto3

client = boto3.client("s3", region_name="eu-north-1")
response = client.list_buckets()
# print(response['Buckets'])


def delete_s3_bucket(bucket_name, region):
    """
    Delete an S3 bucket together with all stored objects.

    :param bucket_name: name of the S3 bucket to delete
    :param region: region of the bucket
    """
    try:
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.object_versions.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass


for bucket in response["Buckets"]:
    if "integ-tests-" in bucket["Name"]:

        print(bucket["Name"])
        delete_s3_bucket(bucket["Name"], "eu-north-1")

#     s3 = boto3.resource('s3')
#     s3_bucket = s3.Bucket(bucket['Name'])
#     bucket_versioning = s3.BucketVersioning(bucket['Name'])
#     if bucket_versioning.status == 'Enabled':
#         s3_bucket.object_versions.delete()
#     else:
#         s3_bucket.objects.all().delete()
#     response = client.delete_bucket(Bucket=bucket['Name'])
