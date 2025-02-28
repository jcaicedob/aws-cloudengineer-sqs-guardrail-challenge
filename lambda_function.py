import boto3
import logging
import os

# Logging configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sqs_client = boto3.client('sqs')
kms_client = boto3.client('kms')
ec2_client = boto3.client('ec2')
sns_client = boto3.client('sns')

# Configure SNS Topic ARN from env variable
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')
REQUIRED_TAGS = ['Name', 'Created By', 'Cost Center']

def check_vpc_endpoint():
    """Check if SQS VPC endpoint exists"""
    try:
        response = ec2_client.describe_vpc_endpoints(Filters=[
            {'Name': 'service-name', 'Values': ['com.amazonaws.sqs']}
        ])
        return len(response.get('VpcEndpoints', [])) > 0
    except Exception as e:
        logger.error(f"Error while checking VPC endpoint: {e}")
        return False

def check_encryption(queue_url):
    """Check if the SQS queue has encryption enabled"""
    try:
        attributes = sqs_client.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=['KmsMasterKeyId']
        )
        return 'KmsMasterKeyId' in attributes.get('Attributes', {})
    except Exception as e:
        logger.error(f"Error verifying encryption in {queue_url}: {e}")
        return False

def check_cmk_key(queue_url):
    """Check if the queue uses a CMK instead of an AWS managed key"""
    try:
        attributes = sqs_client.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=['KmsMasterKeyId']
        )
        key_id = attributes.get('Attributes', {}).get('KmsMasterKeyId')
        if key_id:
            key_info = kms_client.describe_key(KeyId=key_id)
            return key_info['KeyMetadata']['KeyManager'] == 'CUSTOMER'
        return False
    except Exception as e:
        logger.error(f"Eror checking CMK in {queue_url}: {e}")
        return False

def check_tags(queue_url):
    """Check that the queue has the required labels"""
    try:
        response = sqs_client.list_queue_tags(QueueUrl=queue_url)
        tags = response.get('Tags', {})
        return all(tag in tags for tag in REQUIRED_TAGS)
    except Exception as e:
        logger.error(f"Error checking lables in {queue_url}: {e}")
        return False

def send_alert(message):
    """Send an alert to SNS in case of verification failures"""
    if SNS_TOPIC_ARN:
        sns_client.publish(TopicArn=SNS_TOPIC_ARN, Message=message)
    logger.error(message)

def lambda_handler(event, context):
    """Main function that performs required checks"""
    # queue_url = event.get('detail', {}).get('responseElements', {}).get('queueUrl')
    queue_url = event['detail']['responseElements']['queueUrl']
    print(queue_url)
    if not queue_url:
        send_alert("SQS queue URL not provided.")
        return
    
    checks = {
        'VPC-Endpoint': check_vpc_endpoint(),
        'Encryption-at-Rest': check_encryption(queue_url),
        'CMK': check_cmk_key(queue_url),
        'Tag-Verification': check_tags(queue_url)
    }
    
    failed_checks = [check for check, result in checks.items() if not result]
    
    if failed_checks:
        message = f"The following checks failed in {queue_url}: {', '.join(failed_checks)}"
        send_alert(message)
    else:
        logger.info(f"All checks passed in {queue_url}.")
