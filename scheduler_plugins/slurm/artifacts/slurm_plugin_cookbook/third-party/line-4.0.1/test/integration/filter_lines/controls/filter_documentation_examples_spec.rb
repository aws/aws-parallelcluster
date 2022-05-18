control 'filter_documentation_examples' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/example/after') do
    its(:content) { should eq "line1#{eol}line2#{eol}add1#{eol}add2#{eol}" }
  end

  describe file('/example/before') do
    its(:content) { should eq "line1#{eol}add1#{eol}add2#{eol}line2#{eol}" }
  end

  describe file('/example/between') do
    its(:content) { should eq "line1#{eol}line2#{eol}add1#{eol}add2#{eol}line3#{eol}" }
  end

  describe file('/example/comment') do
    its(:content) { should eq "#      line1#{eol}#      line2#{eol}line#{eol}" }
  end

  describe file('/example/delete_between') do
    its(:content) { should eq "line1#{eol}del1#{eol}del2#{eol}line2#{eol}line3#{eol}" }
  end

  describe file('/example/missing') do
    its(:content) { should eq "line1#{eol}line2#{eol}add1#{eol}add2#{eol}" }
  end

  describe file('/example/replace') do
    its(:content) { should eq "line1#{eol}add1#{eol}add2#{eol}" }
  end

  describe file('/example/replace_between') do
    its(:content) { should eq "line1#{eol}rep1#{eol}rep2#{eol}line3#{eol}" }
  end

  describe file('/example/replace_between_include_bounds') do
    its(:content) { should eq "rep1#{eol}rep2#{eol}" }
  end

  describe file('/example/replace_between_using_next') do
    its(:content) { should eq "line1 = rep1#{eol}rep2;#{eol}line3;#{eol}" }
  end

  describe file('/example/replace_between_include_first_boundary') do
    its(:content) { should eq "rep1#{eol}rep2#{eol}line3#{eol}" }
  end

  describe file('/example/stanza') do
    its(:content) { should eq "[first]#{eol}  line2 = addme#{eol}  line1 = new1#{eol}[second]#{eol}  line3 = add3#{eol}  line2 = value2#{eol}" }
  end

  describe file('/example/substitute') do
    its(:content) { should eq "line1 text here#{eol}line2 text new#{eol}" }
  end
end
