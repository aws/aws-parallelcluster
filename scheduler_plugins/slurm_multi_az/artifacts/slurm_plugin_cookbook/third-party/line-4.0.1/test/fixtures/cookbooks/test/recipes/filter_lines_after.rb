#
# Verify the results of using the after filter
#

directory '/tmp'

# ==================== after filter =================

insert_lines = %w(line1 line2 line3)
text_lines = "line1\nline2\nline3\n"
match_pattern = /^COMMENT ME|^HELLO/

# ==================== after filter =================

template '/tmp/after' do
  source 'samplefile.erb'
end

template '/tmp/after_text' do
  source 'samplefile.erb'
end

file '/tmp/empty' do
  content ''
end

filter_lines 'Missing file ok' do
  path '/tmp/missing'
  filters after: [match_pattern, text_lines]
end

filter_lines 'Missing file fails' do
  path '/tmp/missing'
  ignore_missing false
  ignore_failure true
  filters after: [match_pattern, text_lines]
end

filter_lines 'Empty file' do
  path '/tmp/empty'
  filters after: [match_pattern, text_lines]
end

filter_lines 'Insert lines after match - text' do
  sensitive false
  path '/tmp/after_text'
  filters after: [match_pattern, text_lines]
  backup false
end

filter_lines 'Insert lines after match' do
  sensitive false
  path '/tmp/after'
  filters after: [match_pattern, insert_lines]
  backup true
end

filter_lines 'Insert lines after match redo' do
  sensitive false
  path '/tmp/after'
  filters after: [match_pattern, insert_lines]
end

template '/tmp/after_first' do
  source 'samplefile.erb'
end

filter_lines 'Insert lines after first match' do
  sensitive false
  path '/tmp/after_first'
  filters after: [match_pattern, insert_lines, :first]
end

template '/tmp/after_last' do
  source 'samplefile.erb'
end

filter_lines 'Insert lines after last match' do
  sensitive false
  path '/tmp/after_last'
  filters after: [match_pattern, insert_lines, :last]
end

# Without safe mode lines can be inserted after every run
# In most cases repeated inserts is a bad problem. Files can grow endlessly
file '/tmp/safe_bypass' do
  content 'line1'
end
filter_lines 'Bypass safe doit' do
  sensitive false
  path '/tmp/safe_bypass'
  safe false
  filters after: [/line1/, ['line1'], :last]
end
filter_lines 'Bypass safe redo 1' do
  sensitive false
  path '/tmp/safe_bypass'
  safe false
  filters after: [/line1/, ['line1'], :last]
end
filter_lines 'Bypass safe redo 2' do
  sensitive false
  path '/tmp/safe_bypass'
  safe true
  filters after: [/line1/, ['line1'], :last, { safe: false }]
end

file '/tmp/safe_active' do
  content 'line1'
end
filter_lines 'Safe active' do
  sensitive false
  path '/tmp/safe_active'
  safe true
  ignore_failure true
  filters after: [/line1/, ['line1'], :last]
end
