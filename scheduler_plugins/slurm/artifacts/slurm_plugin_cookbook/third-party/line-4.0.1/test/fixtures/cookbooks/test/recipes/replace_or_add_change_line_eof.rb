#
# cookbook::test
#
# Test the replace_or_add resource.
# Change the last line of a file
#

template '/tmp/change_line_eof' do
  source 'text_file.erb'
end

replace_or_add 'change_line_eof' do
  path '/tmp/change_line_eof'
  pattern 'Last line'
  line 'Last line changed'
end

replace_or_add 'change_line_eof redo' do
  path '/tmp/change_line_eof'
  pattern 'Last line'
  line 'Last line changed'
end
