title 'Add_to_list: Test for lists with seperator, entry and terminal characters'
# 18
# 'to empty list' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('empty_delimited_list=("newentry")'))) }
end

# 'add entry that already exists' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(/#{Regexp.escape('last_delimited_list= (|single|)')}/) }
end

# 'add existing entry and new entry' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(/#{Regexp.escape('my @net1918 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "33.33.33.0/24");')}/) }
end
