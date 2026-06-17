# Homebrew formula for Sarathi.
#
# Sarathi is not yet published to PyPI and has no tagged release tarball, so
# this formula installs from the GitHub HEAD by default:
#
#   brew install --HEAD <your-tap>/sarathi
#
# Once a tagged release exists, uncomment the `url`/`sha256` block below and
# drop (or keep, for `--HEAD` builds) the `head` line so `brew install` works
# without the --HEAD flag.
class Sarathi < Formula
  include Language::Python::Virtualenv

  desc "Policy-backed workflow orchestration for AI-assisted delivery (CLI + agent skill)"
  homepage "https://github.com/kulkarni2u/Sarathi"
  license "MIT"

  # No release tarball yet -- install from the repo HEAD.
  head "https://github.com/kulkarni2u/Sarathi.git", branch: "main"

  # TODO: enable these for a tagged release (replace VERSION and pin the sha256
  # of the generated GitHub release tarball):
  # url "https://github.com/kulkarni2u/Sarathi/archive/refs/tags/vVERSION.tar.gz"
  # sha256 "..."

  depends_on "python@3.12"

  # Runtime dependencies (from pyproject.toml: PyYAML, httpx).
  resource "PyYAML" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/b1/df/48c586a5fe32a0f01324ee087459e112ebb7224f646c0b5023f5e79e9956/httpx-0.28.1.tar.gz"
    sha256 "75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc"
  end

  # NOTE: httpx pulls in transitive deps (anyio, certifi, httpcore, h11, idna,
  # sniffio). For a real tap, regenerate the full resource list with:
  #   brew update-python-resources Formula/sarathi.rb
  # and pin each real sha256 from PyPI.
  # TODO: add transitive httpx resources with real sha256 values from PyPI.

  def install
    virtualenv_install_with_resources
  end

  test do
    # `sarathi --help` should succeed and mention the program name.
    output = shell_output("#{bin}/sarathi --help")
    assert_match "sarathi", output.downcase
  end
end
