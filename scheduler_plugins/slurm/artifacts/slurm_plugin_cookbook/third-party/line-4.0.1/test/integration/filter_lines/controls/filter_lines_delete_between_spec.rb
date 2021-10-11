#
# Spec tests for the delete_between filter
#

control 'filter_lines_delete_between - Verify the code to use the delete_between filter.' do
  describe file('/tmp/delete_between') do
    its(:content) { should_not match(/^kernel/) }
  end

  describe file('/tmp/delete_between') do
    its(:content) { should match(/crashkernel/) }
  end

  describe file_ext('/tmp/delete_between') do
    its('size_lines') { should eq 18 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Delete lines between matches redo.*n/) }
  end
end
