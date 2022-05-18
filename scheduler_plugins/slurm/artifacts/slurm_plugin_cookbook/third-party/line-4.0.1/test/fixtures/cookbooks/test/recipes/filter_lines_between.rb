#
# Verify the results of using the between filter
#

directory '/tmp'

# ==================== between filter =================
template '/tmp/between' do
  source 'samplefile3.erb'
end

filter_lines 'Change lines between matches' do
  path '/tmp/between'
  sensitive false
  filters between: [/^empty/, /last_list/, ['add line']]
end

filter_lines 'Change lines between matches redo' do
  path '/tmp/between'
  sensitive false
  filters between: [/^empty/, /last_list/, ['add line']]
end
