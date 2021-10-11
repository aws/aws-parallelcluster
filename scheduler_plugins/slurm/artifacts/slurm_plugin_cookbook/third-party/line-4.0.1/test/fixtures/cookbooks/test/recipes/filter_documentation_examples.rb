# documentation examples
directory '/example'

# Examples for the after filter
file '/example/after' do
  content "line1\nline2\n"
end

addlines = %w(add1 add2)

filter_lines '/example/after' do
  filters(after: [/^line2$/, addlines, :last])
end

# Examples for the before filter
file '/example/before' do
  content "line1\nline2\n"
end

addlines = "add1\nadd2\n"

filter_lines '/example/before' do
  filters(before: [/^line2$/, addlines, :last])
end

# Examples for the between filter
file '/example/between' do
  content "line1\nline2\nline3\n"
end

addlines = "add1\nadd2\n"

filter_lines '/example/between' do
  filters(between: [/^line2$/, /^line3$/, addlines, :last])
end

## Examples for the comment filter
file '/example/comment' do
  content "line1\nline2\nline\n"
end

addlines = "add1\nadd2\n"

filter_lines '/example/comment' do
  filters(comment: [/^line\d+$/, '#', '      '])
end

# Examples for the delete_between filter
file '/example/delete_between' do
  content "line1\ndel1\ndel2\nline2\ndel1\ndel2\nline3\n"
end

filter_lines '/example/delete_between' do
  filters(delete_between: [/^line2$/, /^line3$/, /del/, :last])
end

# Examples for the missing filter
file '/example/missing' do
  content "line1\nline2\n"
end

addlines = "add1\nadd2\n"

filter_lines '/example/missing' do
  filters(missing: [addlines, :after])
end

# Examples for the replace filter
file '/example/replace' do
  content "line1\nline2\n"
end

addlines = "add1\nadd2\n"

filter_lines '/example/replace' do
  filters(replace: [/^line2$/, addlines])
end

# Examples for the replace_between filter
file '/example/replace_between' do
  content "line1\nline2\nline3"
end

replines = "rep1\nrep2\n"

filter_lines '/example/replace_between' do
  filters(replace_between: [/^line1$/, /^line3$/, replines])
end

file '/example/replace_between_include_bounds' do
  content "line1\nline2\nline3"
end

replines = "rep1\nrep2\n"

filter_lines '/example/replace_between_include_bounds' do
  filters(replace_between: [/^line1$/, /^line3$/, replines, :include])
end

file '/example/replace_between_include_first_boundary' do
  content "line1\nline2\nline3"
end

replines = "rep1\nrep2\n"

filter_lines '/example/replace_between_include_first_boundary' do
  filters(replace_between: [/^line1$/, /^line3$/, replines, :first])
end

file '/example/replace_between_using_next' do
  content "line1 = text\nline2;\nline3;"
end

replines = "line1 = rep1\nrep2;\n"

filter_lines '/example/replace_between_using_next' do
  filters(replace_between: [/^line1/, /;$/, replines, [:include, :next]])
end

# Examples for the stanza filter
file '/example/stanza' do
  content "[first]\n  line1 = value1\n[second]\n  line2 = value2\n"
end

filter_lines '/example/stanza' do
  filters([
            { stanza: ['first', { line1: 'new1', line2: 'addme' }] },
            { stanza: ['second', { line3: 'add3' }] },
          ])
end

# Examples for the substitute filter
file '/example/substitute' do
  content "line1 text here\nline2 text here\n"
end

filter_lines '/example/substitute' do
  filters(substitute: [/^line2/, /here/, 'new'])
end
