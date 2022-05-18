#
# Verify the results of using the before filter
#

directory '/tmp'

# ==================== before filter =================

insert_lines = %w(line1 line2 line3)
match_pattern = /^COMMENT ME|^HELLO/

# ==================== before filter =================

template '/tmp/before' do
  source 'samplefile.erb'
  sensitive true
end

template '/tmp/before_first' do
  source 'samplefile.erb'
  sensitive true
end

template '/tmp/before_last' do
  source 'samplefile.erb'
  sensitive true
end

filter_lines 'Insert lines before match' do
  path '/tmp/before'
  sensitive false
  filters before: [match_pattern, insert_lines]
end

filter_lines 'Insert lines before match' do
  path '/tmp/before_first'
  sensitive false
  filters before: [match_pattern, insert_lines, :first]
end

filter_lines 'Insert lines last match' do
  path '/tmp/before_last'
  sensitive false
  filters before: [match_pattern, insert_lines, :last]
end

filter_lines 'Insert lines before match redo' do
  path '/tmp/before'
  sensitive false
  filters before: [match_pattern, insert_lines]
end
