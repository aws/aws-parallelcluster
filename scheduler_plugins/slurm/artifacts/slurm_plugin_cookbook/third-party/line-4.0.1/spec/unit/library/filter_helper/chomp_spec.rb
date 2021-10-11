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

describe 'chomp_array method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.eol = "\n"
  end

  it 'should remove trailing eol from lines in an array' do
    expect(@filt.chomp_array(['line'])).to eq(['line'])
    expect(@filt.chomp_array(["line\n"])).to eq(['line'])
    expect(@filt.chomp_array(%W(line\n line2))).to eq(%w(line line2))
    expect(@filt.chomp_array(%W(line\n line2\n))).to eq(%w(line line2))
    expect(@filt.chomp_array([])).to eq([])
    expect(@filt.chomp_array(["\n"])).to eq([''])
  end
end

describe 'chomp_eol method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.eol = "\n"
  end

  it 'should remove trailing eol' do
    expect(@filt.chomp_eol("line\n")).to eq('line')
  end

  it 'should raise error with embedded eol' do
    expect { @filt.chomp_eol("embedded\ninline") }.to raise_error(ArgumentError)
  end
end
