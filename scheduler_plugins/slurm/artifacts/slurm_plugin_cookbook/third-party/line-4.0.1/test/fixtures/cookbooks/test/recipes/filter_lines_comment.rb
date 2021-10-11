directory '/tmp'

# ==================== comment filter =================
template '/tmp/comment' do
  source 'samplefile3.erb'
end

filter_lines 'Change matching lines to comments' do
  path '/tmp/comment'
  sensitive false
  filters comment: [/last_list/]
end

filter_lines 'Change matching lines to comments redo' do
  path '/tmp/comment'
  sensitive false
  filters comment: [/last_list/]
end
