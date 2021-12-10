#
# Verify the results of using the replace filter
#

directory '/tmp'

# ==================== replace filter =================
insert_lines = %w(line1 line2 line3)
match_pattern = /^COMMENT ME|^HELLO/

template '/tmp/replace' do
  source 'samplefile.erb'
  sensitive true
end

filter_lines 'Replace the matched line' do
  sensitive false
  path '/tmp/replace'
  filters replace: [match_pattern, insert_lines]
end

filter_lines 'Replace the matched line redo' do
  sensitive false
  path '/tmp/replace'
  filters replace: [match_pattern, insert_lines]
end
