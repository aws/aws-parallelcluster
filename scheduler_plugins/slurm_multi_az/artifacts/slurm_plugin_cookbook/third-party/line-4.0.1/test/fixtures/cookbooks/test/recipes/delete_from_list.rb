directory '/tmp'

template '/tmp/samplefile3'

# Delete the first entry in a list with delimited entries
delete_from_list 'Delete Operation 1' do
  path '/tmp/samplefile3'
  pattern 'my @net1918 ='
  delim [', ', '"']
  entry '10.0.0.0/8'
  backup true
end

# # Delete the last entry in a list with delimited entries
delete_from_list 'Delete Operation 2' do
  path '/tmp/samplefile3'
  pattern 'my @net1918 ='
  delim [', ', '"']
  entry '192.168.0.0/16'
end

delete_from_list 'Delete Operation 3' do
  path '/tmp/samplefile3'
  pattern 'People to call:'
  delim [', ']
  entry 'Joe'
end

delete_from_list 'Delete Operation 4' do
  path '/tmp/samplefile3'
  pattern 'People to call:'
  delim [', ']
  entry 'Karen'
end

delete_from_list 'Delete Operation 5' do
  path '/tmp/samplefile3'
  pattern 'multi = '
  delim [', ', '[', ']']
  entry '425'
end

delete_from_list 'grub.conf - Remove rhgb' do
  path '/tmp/samplefile3'
  pattern '^\\s*kernel '
  delim [' ']
  entry 'rhgb'
end

delete_from_list 'grub.conf - Remove quiet' do
  path '/tmp/samplefile3'
  pattern '^\\s*kernel '
  delim [' ']
  entry 'quiet'
end

delete_from_list 'delimiter is 2 spaces' do
  path '/tmp/samplefile3'
  pattern '^double  space'
  delim ['  ']
  entry 'separator'
end

delete_from_list 'delimiter is comma and space' do
  path '/tmp/samplefile3'
  pattern '^list, comma-space'
  delim [', ']
  entry 'third'
end

delete_from_list 'delimiter is comma and space last entry' do
  path '/tmp/samplefile3'
  pattern '^list, comma-space'
  delim [', ']
  entry 'fifth'
end

delete_from_list 'delimiter is space and comma' do
  path '/tmp/samplefile3'
  pattern '^list ,space-comma'
  delim [' ,']
  entry 'third'
end

delete_from_list 'delimiter is space and comma last entry' do
  path '/tmp/samplefile3'
  pattern '^list ,space-comma'
  delim [' ,']
  entry 'fifth'
  ignore_missing true
end

file '/tmp/emptyfile' do
  content ''
end
delete_from_list 'empty file should remain unchanged' do
  path '/tmp/emptyfile'
  pattern 'list='
  delim [' ']
  entry 'not_there'
end

file 'prep for test /tmp/nofilehere' do
  path '/tmp/nofilehere'
  action :delete
end

delete_from_list 'missing_file fail' do
  path '/tmp/nofilehere'
  pattern 'multi = '
  delim [', ', '[', ']']
  entry '425'
  ignore_missing false
  ignore_failure true
end

delete_from_list 'missing_file' do
  path '/tmp/nofilehere'
  pattern 'multi = '
  delim [', ', '[', ']']
  entry '425'
end

file '/tmp/ends_with_test_last_entry' do
  content 'GRUB_CMDLINE_LINUX="rd.lvm.lv=centos/root rd.lvm quiet elevator=noop"'
end

delete_from_list '/tmp/ends_with_test_last_entry' do
  path      '/tmp/ends_with_test_last_entry'
  pattern   'GRUB_CMDLINE_LINUX='
  delim     [' ']
  entry     'elevator=noop'
  ends_with '"'
  sensitive false
end

file '/tmp/ends_with_test_middle_entry' do
  content 'GRUB_CMDLINE_LINUX="rd.lvm.lv=centos/root rd.lvm quiet elevator=noop"'
end

delete_from_list '/tmp/ends_with_test_middle_entry' do
  path      '/tmp/ends_with_test_middle_entry'
  pattern   'GRUB_CMDLINE_LINUX='
  delim     [' ']
  entry     'rd.lvm'
  ends_with '"'
  sensitive false
end
