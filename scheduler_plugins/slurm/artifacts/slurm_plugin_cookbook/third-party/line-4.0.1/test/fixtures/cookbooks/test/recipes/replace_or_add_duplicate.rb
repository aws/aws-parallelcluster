#
# cookbook::test
#
# Test the replace_or_add resource.
# Change duplicate lines
#

template '/tmp/duplicate' do
  source 'text_file.erb'
end

template '/tmp/duplicate_replace_only' do
  source 'text_file.erb'
end

replace_or_add 'duplicate' do
  path '/tmp/duplicate'
  pattern 'Identical line'
  line 'Replace duplicate lines'
end

replace_or_add 'duplicate redo' do
  path '/tmp/duplicate'
  pattern 'Identical line'
  line 'Replace duplicate lines'
end

replace_or_add 'duplicate_replace_only' do
  path '/tmp/duplicate_replace_only'
  replace_only true
  pattern 'Identical line'
  line 'Replace duplicate lines'
end
