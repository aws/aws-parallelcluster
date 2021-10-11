#
# cookbook::test
#
# Test the replace_or_add resource.
# Add a line that does not match the pattern
#

template '/tmp/unmatched' do
  source 'text_file.erb'
end

replace_or_add 'unmatched' do
  path '/tmp/unmatched'
  pattern 'Does not match'
  line 'Unmatched line'
end

replace_or_add 'unmatched redo' do
  path '/tmp/unmatched'
  pattern 'Does not match'
  line 'Unmatched line'
end
