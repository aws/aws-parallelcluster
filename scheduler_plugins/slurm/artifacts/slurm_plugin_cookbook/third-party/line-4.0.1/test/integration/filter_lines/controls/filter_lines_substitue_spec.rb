#
# Spec tests for the substitute filter
#

control 'filter_lines_substitute - Verify the code to use the substitute filter.' do
  describe file('/tmp/substitute') do
    its(:content) { should match(/start_list/) }
  end

  describe file_ext('/tmp/substitute') do
    its('size_lines') { should eq 20 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Substitute string for matching pattern redo.*n/) }
  end
end
