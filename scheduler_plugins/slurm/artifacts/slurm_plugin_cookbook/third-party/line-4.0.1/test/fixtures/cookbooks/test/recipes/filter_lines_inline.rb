#
# Test an inline filter
#

directory '/tmp'

# ==================== Inline proc filters =================

template '/tmp/samplefile' do
end

filter_lines 'Do nothing' do
  sensitive false
  path '/tmp/samplefile'
  filters proc { |current| current }
end

template '/tmp/reverse' do
  source 'samplefile.erb'
end

filter_lines 'Reverse line text' do
  sensitive false
  path '/tmp/reverse'
  filters proc { |current| current.map(&:reverse) }
end
