append_if_no_line 'missing_file fail' do
  path '/tmp/nofilehere'
  line 'add this line'
  ignore_missing false
end
