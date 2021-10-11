require 'rspec_helper'
require 'ostruct'

link_lines = `egrep -R 'https:\/\/github.com\/sous-chefs\/line' *`.split("\n")
line_files = link_lines.map do |line|
  md = %r{\]\(https://github.com/sous-chefs/line/blob/master/(.*)\)}.match(line)
  md ? md[1] : nil
end

describe 'linked documentation files exist' do
  line_files.compact.each do |file|
    it "File #{file} should exist" do
      expect(File.exist?(file)).to eq true
    end
  end
end
