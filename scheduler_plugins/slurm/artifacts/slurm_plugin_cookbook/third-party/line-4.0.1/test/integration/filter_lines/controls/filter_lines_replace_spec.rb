#
# Spec tests for the replace filter
#

control 'filter_lines_replace - Verify the code to use the replace filter.' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/replace') do
    its(:content) { should match(/\Aline1#{eol}line2#{eol}line3#{eol}# UN/m) }
  end

  describe file_ext('/tmp/replace') do
    its('size_lines') { should eq 9 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Replace the matched line redo.*n/) }
  end
end
