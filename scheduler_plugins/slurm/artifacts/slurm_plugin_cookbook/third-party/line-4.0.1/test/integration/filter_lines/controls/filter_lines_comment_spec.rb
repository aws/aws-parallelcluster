#
# Spec tests for the comment filter
#

control 'filter_lines_comment - Verify the code to use the comment filter.' do
  describe file('/tmp/comment') do
    its(:content) { should match(/# last_list/) }
  end

  describe file_ext('/tmp/comment') do
    its('size_lines') { should eq 20 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Change matching lines to comments redo.*n/) }
  end
end
