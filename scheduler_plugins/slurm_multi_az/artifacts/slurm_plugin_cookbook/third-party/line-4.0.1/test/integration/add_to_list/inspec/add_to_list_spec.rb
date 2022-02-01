title 'Add to list'
eol = os.family == 'windows' ? "\r\n" : "\n"

describe file('/tmp/samplefile3') do
  its(:content) { should match(/empty_list=newentry/) }
end

# It should not re-add an existing item
describe file('/tmp/samplefile3') do
  its(:content) { should match(%r{DEFAULT_APPEND="resume=/dev/sda2 splash=silent crashkernel=256M-:128M showopts addtogrub"}) }
end

# Add to an empty list
describe file('/tmp/samplefile3') do
  its(:content) { should match(/empty_delimited_list=\(\"newentry\"\)/) }
end

# The last line has an eol
describe file('/tmp/samplefile3') do
  its(:content) { should match(/^last line#{eol}/) }
end

# An empty unchanged file stays that way
describe file('/tmp/emptyfile') do
  its(:size) { should eq 0 }
end
