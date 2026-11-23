# Upgrade Slurm in an AWS ParallelCluster cluster

The scripts in this directory are the ones the wiki page
[Upgrade Slurm in an AWS ParallelCluster cluster](https://github.com/aws/aws-parallelcluster/wiki/Upgrade-Slurm-in-an-AWS-ParallelCluster-cluster)
links to. The integration tests under `tests/integration-tests` run these same files, unchanged, so what is tested is
what the page hands out.

| Script | Page section | What it does |
| --- | --- | --- |
| `rebuild_slurm.sh` | Step 4 | Builds the new Slurm release with the options ParallelCluster used and swaps it into `/opt/slurm`. Does not stop or start anything. |
| `slurm_upgrade.sh upgrade` | Steps 2, 3, 4, 5, 7 and Appendix A | Refuses a release that is not newer than the installed one, then stops the daemons, backs up the Slurm state and installation, runs `rebuild_slurm.sh`, starts the daemons back (slurmdbd first, in the foreground until the accounting database is converted) and runs the checks that need no compute node. |
| `slurm_upgrade.sh rollback` | Appendix D | Stops the daemons, restores `/opt/slurm` and the controller state in place from the backups of Step 3 (archiving what they held first), restores the accounting database when a dump is given (and refuses a cross major release rollback of a node that runs slurmdbd without one), and starts the daemons back. |
| `slurm_accounting_database.sh` | Step 3.2 and Appendix D.4 | Dumps and restores the Slurm accounting database with `mysqldump` and `mysql`, using the connection settings of `slurmdbd.conf`. |

Keep the three files together in one directory on the node: `slurm_upgrade.sh` runs the other two from its own
directory.

```bash
# On the head node (or on the external Slurmdbd instance, Appendix A), after Step 1 and with your backups planned:
sudo SLURM_VERSION_NEW=slurm-25-11-8-1 ./slurm_upgrade.sh upgrade

# Without internet access, point Step 4 at the ParallelCluster bucket of your Region:
sudo SLURM_VERSION_NEW=slurm-25-11-8-1 \
     SLURM_SOURCE_URL=https://us-east-1-aws-parallelcluster.s3.us-east-1.amazonaws.com/archives/dependencies/slurm/slurm-25-11-8-1.tar.gz \
     ./slurm_upgrade.sh upgrade

# If the new version does not work (Appendix D), with the compute fleet stopped again:
sudo ./slurm_upgrade.sh rollback [--accounting-backup /opt/slurm_accounting_backup_<timestamp>.sql.gz]
```

What the scripts leave to you, exactly as the page does: stopping and starting the compute fleet (Steps 1 and 6),
scaling the login nodes down and back (Appendix E), backing up the accounting database before a major release upgrade
(Step 3.2, `slurm_accounting_database.sh backup` does it for a MySQL compatible database), rebuilding plugins built
against Slurm (Appendix B) and running your own jobs afterwards (Step 7).
