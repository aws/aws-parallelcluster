#
# cookbook::test
#
# Test the replace_or_add resource.
# Add a line that exactly matches the specified pattern.
#

template '/tmp/add_a_line_matching_pattern' do
  source 'text_file.erb'
end

replace_or_add 'add_a_line_matching_pattern' do
  path '/tmp/add_a_line_matching_pattern'
  pattern 'Add another line'
  line 'Add another line'
end

replace_or_add 'add_a_line_matching_pattern redo' do
  path '/tmp/add_a_line_matching_pattern'
  pattern 'Add another line'
  line 'Add another line'
end
