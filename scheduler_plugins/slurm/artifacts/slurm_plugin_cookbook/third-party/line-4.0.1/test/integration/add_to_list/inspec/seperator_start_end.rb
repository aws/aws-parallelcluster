title 'Add_to_list: Tests for lists with seperator, start and end delimiters'
# 'add first entry' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('wo3d_empty=[single]'))) }
end

# 'add existing and new entry' do
describe file('/tmp/samplefile3') do
  its(:content) { should match(Regexp.new(Regexp.escape('wo3d_list=[first3],[second3],[third3]'))) }
end
