#
# slurm.csh:
#     Sets the C shell user environment for slurm commands
#
set path = ($path /opt/slurm/bin)
if ( ${?MANPATH} ) then
  setenv MANPATH ${MANPATH}:/opt/slurm/share/man
else
  setenv MANPATH :/opt/slurm/share/man
endif
