#
# Spec tests for the stanza filter
#

control 'filter_lines_stanza - Verify the code to use the stanza filter.' do
  describe file('/tmp/stanza') do
    its(:content) { should match(/lowercase-names = false/) }
    its(:content) { should match(/addme = option/) }
    its(:content) { should match(/mscldap-timeout = 5/) }
  end

  describe file_ext('/tmp/stanza') do
    its('size_lines') { should eq 26 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Change stanza values redo.*n/) }
  end
end
