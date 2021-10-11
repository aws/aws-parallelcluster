replace_or_add 'missing_file fail' do
  path '/tmp/nofilehere'
  pattern 'multi = '
  line 'add this line'
  ignore_missing false
end
