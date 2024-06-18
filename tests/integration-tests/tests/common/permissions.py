def create_image_roles(create_roles_stack):
    # Create build image roles
    image_roles_stack = create_roles_stack(
        stack_prefix="integ-tests-iam-image-roles", roles_file="image-roles.cfn.yaml"
    )
    lambda_cleanup_role = image_roles_stack.cfn_outputs["BuildImageLambdaCleanupRole"]
    instance_profile = image_roles_stack.cfn_outputs["BuildImageInstanceProfile"]
    # instance_role = image_roles_stack.cfn_outputs["BuildImageInstanceRole"]
    return instance_profile, lambda_cleanup_role
