#
# Spec tests for the after filter
#

control 'filter_lines_after - Verify the code to use the after filter.' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/after_text') do
    its(:content) { should match(/HELLO THERE I AM DANGERFILE#{eol}line1#{eol}line2#{eol}line3#{eol}# UN/m) }
    its(:content) { should match(/COMMENT ME AND I STOP YELLING I PROMISE#{eol}line1#{eol}line2#{eol}line3#{eol}int/m) }
  end
  describe file_ext('/tmp/after_text') do
    its('size_lines') { should eq 11 }
  end

  describe file('/tmp/after') do
    its(:content) { should match(/HELLO THERE I AM DANGERFILE#{eol}line1#{eol}line2#{eol}line3#{eol}# UN/m) }
    its(:content) { should match(/COMMENT ME AND I STOP YELLING I PROMISE#{eol}line1#{eol}line2#{eol}line3#{eol}int/m) }
  end
  describe file_ext('/tmp/after') do
    its('size_lines') { should eq 11 }
  end

  describe file('/tmp/after_first') do
    its(:content) { should match(/HELLO THERE I AM DANGERFILE#{eol}line1#{eol}line2#{eol}line3#{eol}# UN/m) }
    its(:content) { should match(/COMMENT ME AND I STOP YELLING I PROMISE#{eol}int/m) }
  end
  describe file_ext('/tmp/after_last') do
    its('size_lines') { should eq 8 }
  end

  describe file('/tmp/after_last') do
    its(:content) { should match(/HELLO THERE I AM DANGERFILE#{eol}# UNCOMMENT/m) }
    its(:content) { should match(/COMMENT ME AND I STOP YELLING I PROMISE#{eol}line1#{eol}line2#{eol}line3#{eol}int/m) }
  end
  describe file_ext('/tmp/after_last') do
    its('size_lines') { should eq 8 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Insert lines after match redo.*n/) }
  end

  describe file('/tmp/safe_bypass') do
    its(:content) { should match(/line1/) }
  end
  describe file_ext('/tmp/safe_bypass') do
    its('size_lines') { should eq 4 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Bypass safe doit.*y/) }
    its(:content) { should match(/Bypass safe redo 1.*y/) }
    its(:content) { should match(/Bypass safe redo 2.*y/) }
    its(:content) { should match(/filter_lines\[Missing file ok\] n/) }
    its(:content) { should match(/filter_lines\[Missing file fails\] n/) }
    its(:content) { should match(/filter_lines\[Empty file\] n/) }
  end

  describe file_ext('/tmp/safe_active') do
    its('size_lines') { should eq 1 }
  end
end
