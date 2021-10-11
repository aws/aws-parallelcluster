# ============ multiple filters

control 'filter_lines - Verify the code to use filters. Verify several example filters' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/multiple_filters') do
    its(:content) { should match(/HELLO THERE I AM DANGERFILE#{eol}line1#{eol}line2#{eol}line3#{eol}/m) }
    its(:content) { should match(/COMMENT ME AND I STOP YELLING I PROMISE#{eol}line1#{eol}line2#{eol}line3#{eol}int/m) }
    its(:content) { should_not match(/# UNCOMMENT/) }
  end
  describe file_ext('/tmp/multiple_filters') do
    its('size_lines') { should eq 10 }
  end
end
