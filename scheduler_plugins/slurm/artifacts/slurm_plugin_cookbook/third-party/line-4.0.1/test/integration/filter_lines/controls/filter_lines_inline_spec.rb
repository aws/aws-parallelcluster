#
# Spec tests for the inline filters
#

control 'filter_lines - Verify the code to use adhoc filters.' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  # ============ inline

  # do nothing
  describe file('/tmp/samplefile') do
    its(:content) { should match(/^HELLO THERE I AM DANGERFILE.*last line#{eol}$/m) }
  end

  describe file_ext('/tmp/samplefile') do
    its('size_lines') { should eq 5 }
  end

  # reverse the characters in each line
  describe file('/tmp/reverse') do
    its(:content) { should match(/OLLEH#{eol}/) }
    its(:content) { should match(/^enil tsal#{eol}/) }
  end
end
