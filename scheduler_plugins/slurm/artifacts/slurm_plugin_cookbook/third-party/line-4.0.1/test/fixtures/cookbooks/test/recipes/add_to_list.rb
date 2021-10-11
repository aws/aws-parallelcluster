directory '/tmp'

template '/tmp/samplefile3'

# test lists with an item seperator
add_to_list 'Add to an empty list, seperator' do
  path '/tmp/samplefile3'
  pattern 'empty_list='
  delim [' ']
  entry 'newentry'
  backup true
end

add_to_list 'Add an entry to an empty list, seperator' do
  path '/tmp/samplefile3'
  pattern 'last_list='
  delim [' ']
  entry 'single'
end

add_to_list 'Add a duplicate entry to a list, seperator' do
  path '/tmp/samplefile3'
  pattern 'People to call:'
  delim [', ']
  entry 'Bobby'
end

add_to_list 'Add a new entry to a list, seperator' do
  path '/tmp/samplefile3'
  pattern 'People to call:'
  delim [', ']
  entry 'Harry'
end

# test lists with an item seperator and terminal list string
add_to_list 'Add to an empty list, seperator, terminal' do
  path '/tmp/samplefile3'
  pattern 'DEFAULT_APPEND_EMPTY='
  delim [' ']
  ends_with '"'
  entry 'first'
end

add_to_list 'Add an existing item a list, seperator, terminal' do
  path '/tmp/samplefile3'
  pattern 'DEFAULT_APPEND='
  delim [' ']
  ends_with '"'
  entry 'showopts'
end

add_to_list 'Add a new item to a list, seperator, terminal' do
  path '/tmp/samplefile3'
  pattern 'DEFAULT_APPEND='
  delim [' ']
  ends_with '"'
  entry 'addtogrub'
end

# test lists with an item seperator, item delimiters
add_to_list 'Add an item to an empty list, seperator and item delimiters' do
  path '/tmp/samplefile3'
  pattern 'wo2d_empty='
  delim [',', '"']
  entry 'single'
end

add_to_list 'Add an existing entry to a list, seperator and item delimiters' do
  path '/tmp/samplefile3'
  pattern 'wo2d_list'
  delim [',', '"']
  entry 'first2'
end

add_to_list 'Add a new entry to a list, seperator and item delimiters' do
  path '/tmp/samplefile3'
  pattern 'wo2d_list'
  delim [',', '"']
  entry 'third2'
end

# test lists with an item seperator, item delimiters and a terminal list string
add_to_list 'Add to an empty list with an item seperator, item delimiters and a terminal list string' do
  path '/tmp/samplefile3'
  pattern Regexp.escape('empty_delimited_list=(')
  delim [', ', '"']
  ends_with ')'
  entry 'newentry'
end

add_to_list 'Add an existing entry to a list with an item seperator, item delimiters and a terminal list string' do
  path '/tmp/samplefile3'
  pattern Regexp.escape('last_delimited_list= (')
  delim [',', '|']
  ends_with ')'
  entry 'single'
end

add_to_list 'Add an existing entry to a list with item seperator, item delimiters and a terminal list string' do
  path '/tmp/samplefile3'
  pattern 'my @net1918 ='
  delim [', ', '"']
  ends_with ');'
  entry '172.16.0.0/12'
end

add_to_list 'Add an entry to a list with item seperator, item delimiters and a terminal list string' do
  path '/tmp/samplefile3'
  pattern 'my @net1918 ='
  delim [', ', '"']
  ends_with ');'
  entry '33.33.33.0/24'
end

add_to_list 'Add an existing item to a complex list' do
  path '/tmp/samplefile3'
  pattern 'multi '
  delim [', ', '[', ']']
  ends_with ')'
  entry '818'
end

# test lists with an item seperator, before and after item delimiters
add_to_list 'Add first entry to a list, seperator, item delimiters' do
  path '/tmp/samplefile3'
  pattern 'wo3d_empty='
  delim [',', '[', ']']
  entry 'single'
end

add_to_list 'Add an existing entry, seperator, item delimiters' do
  path '/tmp/samplefile3'
  pattern 'wo3d_list'
  delim [',', '[', ']']
  entry 'first3'
end

add_to_list 'Add a new entry, seperator, item delimiters' do
  path '/tmp/samplefile3'
  pattern 'wo3d_list'
  delim [',', '[', ']']
  entry 'third3'
end

# test lists with an item seperator, before and after item delimiters and a terminal list string
add_to_list 'Add to list using Regexp escaped input' do
  path '/tmp/samplefile3'
  pattern Regexp.escape('empty_3delim=(')
  delim [' ', '[', ']']
  ends_with ')'
  entry 'newentry'
end

file '/tmp/emptyfile' do
  content ''
end

add_to_list 'Empty files that are not changed should stay empty' do
  path '/tmp/emptyfile'
  pattern  'line='
  delim [' ']
  entry 'should_not_be_added'
end

file 'prep for test /tmp/nofilehere' do
  path '/tmp/nofilehere'
  action :delete
end

add_to_list 'missing_file fail' do
  path '/tmp/nofilehere'
  pattern Regexp.escape('empty_delimited_list=(')
  delim [', ', '"']
  ends_with ')'
  entry 'newentry'
  ignore_missing false
  ignore_failure true
end

add_to_list 'missing_file' do
  path '/tmp/nofilehere'
  pattern Regexp.escape('empty_delimited_list=(')
  delim [', ', '"']
  ends_with ')'
  entry 'newentry'
end
