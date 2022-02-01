title 'Add_to_list: List with seperator and terminal characters'

# 'Add the first entry to an empty list'
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('DEFAULT_APPEND_EMPTY=" first"'))) }
end

# 'Add an existing and a new entry to a list'
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('DEFAULT_APPEND="resume=/dev/sda2 splash=silent crashkernel=256M-:128M showopts addtogrub"'))) }
end
