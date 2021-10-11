#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

require 'rspec_helper'
include Line

describe 'string_to_lines  method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.eol = "\n"
  end

  it 'should return an array for a nl string' do
    expect(@filt.string_to_lines("\n")).to eq([])
  end

  it 'should return an array for an empty string' do
    expect(@filt.string_to_lines('')).to eq([])
  end

  it 'should split a string into a line array' do
    expect(@filt.string_to_lines("line\nline2")).to eq(%w(line line2))
  end

  it 'should leave arrays alone' do
    expect(@filt.string_to_lines(%w(line1 line2))).to eq(%w(line1 line2))
  end

  it 'should leave lines in arrays with embedded newlines alone' do
    expect(@filt.string_to_lines(%W(line1\nextra line2))).to eq(%W(line1\nextra line2))
  end
end
