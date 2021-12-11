#
# Spec tests for the replace_between filter
#

control 'filter_lines_replace_between - Verify the code to use the replace_between filter.' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/replace_between') do
    its(:content) { should match(/FOOL#{eol}line1#{eol}line2#{eol}line3#{eol}int/m) }
  end

  describe file_ext('/tmp/replace_between') do
    its('size_lines') { should eq 7 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Replace the lines between matches redo.*n/) }
  end
end
