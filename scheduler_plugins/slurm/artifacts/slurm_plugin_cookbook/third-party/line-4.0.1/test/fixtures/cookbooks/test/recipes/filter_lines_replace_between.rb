#
# Verify the results of using the replace_between filter
#

directory '/tmp'

# ==================== replace_between filter =================
insert_lines = %w(line1 line2 line3)
start_pattern = /COMMENT/
end_pattern = /main/

template '/tmp/replace_between' do
  source 'samplefile.erb'
  sensitive true
end

filter_lines 'Replace the lines between matches' do
  sensitive false
  path '/tmp/replace_between'
  filters replace_between: [start_pattern, end_pattern, insert_lines]
end

filter_lines 'Replace the lines between matches redo' do
  sensitive false
  path '/tmp/replace_between'
  filters replace_between: [start_pattern, end_pattern, insert_lines]
end
