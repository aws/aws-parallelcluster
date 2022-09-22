#!/bin/bash
set -ex
. "/etc/parallelcluster/cfnconfig"


if [[ $cfn_node_type == "HeadNode" ]]; then
    # Override create_fleet attributes
    cat > /opt/slurm/etc/pcluster/create_fleet_overrides.json << 'EOF'
{
    "fleet": {
        "fleet-1": {
            "TagSpecifications": [
                 {
                    "ResourceType": "instance",
                    "Tags": [
                        {
                            "Key": "overridefleet",
                            "Value": "overridefleet"
                        }
                    ]
                }
            ]
        }
    }
}
EOF

    # Override run_instances attributes
    cat > /opt/slurm/etc/pcluster/run_instances_overrides.json << 'EOF'
{
    "single": {
        "single-1": {
            "TagSpecifications": [
                 {
                    "ResourceType": "instance",
                    "Tags": [
                        {
                            "Key": "overridesingle",
                            "Value": "overridesingle"
                        }
                    ]
                }
            ]
        }
    }
}
EOF
fi
