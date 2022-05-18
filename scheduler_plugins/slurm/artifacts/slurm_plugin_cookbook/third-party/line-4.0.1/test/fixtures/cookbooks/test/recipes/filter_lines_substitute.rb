#
# Verify the results of using the substitute filter
#

directory '/tmp'

# ==================== substitute filter =================
template '/tmp/substitute' do
  source 'samplefile3.erb'
end

filter_lines 'Substitute string for matching pattern' do
  path '/tmp/substitute'
  filters substitute: [/last/, /last_list/, 'start_list']
end

filter_lines 'Substitute string for matching pattern redo' do
  path '/tmp/substitute'
  filters substitute: [/last/, /last_list/, 'start_list']
end
