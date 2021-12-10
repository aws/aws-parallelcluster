title 'Add_to_list: Tests for lists with seperator, start and end, terminal characters'

# 'add to an empty list' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(/#{Regexp.escape('empty_3delim=([newentry])')}/) }
end

# 'add existing entry and new entry to a list' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('multi = ([310], [323], [818])'))) }
end
