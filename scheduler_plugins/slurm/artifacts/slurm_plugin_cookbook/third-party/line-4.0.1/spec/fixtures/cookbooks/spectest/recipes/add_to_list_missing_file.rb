add_to_list 'missing_file fail' do
  path '/tmp/nofilehere'
  pattern Regexp.escape('empty_delimited_list=(')
  delim [', ', '"']
  ends_with ')'
  entry 'newentry'
  ignore_missing false
end
