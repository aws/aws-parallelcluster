#
# Test combinations of filters and edge cases
#

directory '/tmp'

insert_lines = %w(line1 line2 line3)
match_pattern = /^COMMENT ME|^HELLO/

# ==================== Multiple filters =================

template '/tmp/multiple_filters' do
  source 'samplefile.erb'
  sensitive true
end

filter_lines 'Multiple before and after match' do
  path '/tmp/multiple_filters'
  sensitive false
  filters(
    [
      # insert lines before the last match
      { before: [match_pattern, insert_lines, :last] },
      # insert lines after the last match
      { after:  [match_pattern, insert_lines, :last] },
      # delete comment lines
      proc { |current| current.select { |line| line !~ /^#/ } },
    ]
  )
end

filter_lines 'Multiple before and after match redo' do
  path '/tmp/multiple_filters'
  sensitive false
  filters(
    [
      # insert lines before the last match
      { before: [match_pattern, insert_lines, :last] },
      # insert lines after the last match
      { after:  [match_pattern, insert_lines, :last] },
      # delete comment lines
      proc { |current| current.select { |line| line !~ /^#/ } },
    ]
  )
end

# =====================

file '/tmp/emptyfile' do
  content ''
end

filter_lines 'Do nothing to the empty file' do
  path '/tmp/emptyfile'
  sensitive false
  filters proc { |current| current }
end
