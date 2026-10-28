"""A fresh install can generate video thumbnails without system ffmpeg on PATH."""
from pathlib import Path
import subprocess,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
from spt.server import covers

class BundledVideoToolTests(unittest.TestCase):
    def test_bundled_tool_creates_a_real_video_cover(self):
        binary=covers.bundled_ffmpeg()
        if not binary:self.skipTest('Install requirements.txt for bundled video tool')
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'示例视频.mp4';target=root/'thumbs'/'frame.jpg';target.parent.mkdir()
            subprocess.run([binary,'-v','error','-f','lavfi','-i','color=c=red:s=1280x720:d=0.2','-c:v','mpeg4','-y',str(source)],check=True,capture_output=True)
            original=source.read_bytes();owner=SimpleNamespace(issues=[])
            with patch.object(covers.shutil,'which',return_value=None),patch.object(covers,'on_mac',return_value=False):
                covers.build(source,target,owner,root)
            self.assertEqual(owner.issues,[])
            self.assertEqual(source.read_bytes(),original)
            with Image.open(target) as image:self.assertEqual(image.size,(640,360))
if __name__=='__main__':unittest.main()
