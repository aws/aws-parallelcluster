title 'Add_to_list: Tests for lists with seperator and entry delimiters'

# 'Add first entry do an empty list' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('wo2d_empty="single"'))) }
end

# 'Add existing and new entry' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('wo2d_list="first2","second2","third2"'))) }
end
