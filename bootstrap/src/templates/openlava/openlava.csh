#
# cshrc.lsf:
#     Sets the C shell user environment for openlava commands
#
setenv LSF_ENVDIR /opt/openlava-2.2/etc
set path = ($path /opt/openlava-2.2/bin)
if ( ${?MANPATH} ) then
  setenv MANPATH ${MANPATH}:/opt/openlava-2.2/share/man
else
  setenv MANPATH :/opt/openlava-2.2/share/man
endif
