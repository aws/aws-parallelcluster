#
# Verify the results of using the delete_between filter
#

directory '/tmp'

# ==================== delete_between filter =================
template '/tmp/delete_between' do
  source 'samplefile3.erb'
end

filter_lines 'Delete lines between matches' do
  path '/tmp/delete_between'
  sensitive false
  filters delete_between: [/^empty_list/, /^list/, /kernel/]
end

filter_lines 'Delete lines between matches redo' do
  path '/tmp/delete_between'
  sensitive false
  filters delete_between: [/^empty_list/, /^list/, /kernel/]
end
