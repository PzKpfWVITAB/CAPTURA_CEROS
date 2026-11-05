"""
Pruebas automatizadas del motor de análisis, captura local, aplicación y rollback.
"""

import os
import tempfile
import unittest

from src.naming_engine import build_proposals, parse_folder_name, scan_directory
from src.storage import LocalCaptureStore


class TestCapturaCerosPipeline(unittest.TestCase):
    def test_parse_folder_name_preserves_year_and_revisar(self) -> None:
        delg, yr, suf = parse_folder_name("01_00_00_00_00_00_1985_REVISAR")
        self.assertEqual(delg, "01")
        self.assertEqual(yr, "1985")
        self.assertEqual(suf, "REVISAR")

        delg2, yr2, suf2 = parse_folder_name("01_00_00_00_00_00_1994_REVISAR_3")
        self.assertEqual(delg2, "01")
        self.assertEqual(yr2, "1994")
        self.assertEqual(suf2, "REVISAR_3")

        delg3, yr3, suf3 = parse_folder_name("01_00_00_00_00_00_1996")
        self.assertEqual(delg3, "01")
        self.assertEqual(yr3, "1996")
        self.assertEqual(suf3, "REVISAR")

    def test_scan_and_local_capture_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            folder_path = os.path.join(tmp_root, "01_00_00_00_00_00_1985_REVISAR")
            os.makedirs(folder_path)

            # Crear 2 PDFs en ceros y 1 PDF con datos que debe ignorarse
            zero_pdf_1 = os.path.join(folder_path, "01_00_00_00_00_00_0000_0001_00.pdf")
            zero_pdf_2 = os.path.join(folder_path, "01_00_00_00_00_00_0000_0002_00.pdf")
            non_zero_pdf = os.path.join(folder_path, "01_01_01_00_00_00_1991_0001_00.pdf")

            for p in (zero_pdf_1, zero_pdf_2, non_zero_pdf):
                with open(p, "wb") as f:
                    f.write(b"%PDF-1.4 dummy")

            analysis = scan_directory(folder_path)
            self.assertEqual(len(analysis.pdfs_to_rename), 2)
            self.assertEqual(len(analysis.pdfs_ignored), 1)
            self.assertEqual(analysis.detected_year, "1985")

            prop_folder, updated_pdfs = build_proposals(
                analysis,
                delegacion="01",
                seccion="02",
                libro="05",
                tomo="01_AUXILIAR",
                volumen="03",
                fraccionamiento="00",
                anio="1985",
                suffix="REVISAR",
            )
            self.assertEqual(prop_folder, "01_02_05_01_AUXILIAR_03_00_1985_REVISAR")
            self.assertEqual(
                updated_pdfs[0].proposed_name,
                "01_02_05_01_AUXILIAR_03_00_1985_0001_00.pdf",
            )
            self.assertEqual(
                updated_pdfs[1].proposed_name,
                "01_02_05_01_AUXILIAR_03_00_1985_0002_00.pdf",
            )

            # Probar guardado local sin tocar archivos físicos
            db_file = os.path.join(tmp_root, "test_capturas.db")
            store = LocalCaptureStore(db_path=db_file)
            cid = store.save_capture(
                original_folder_path=analysis.folder_path,
                original_folder_name=analysis.folder_name,
                proposed_folder_name=prop_folder,
                delegacion="01",
                seccion="02",
                libro="05",
                tomo="01_AUXILIAR",
                volumen="03",
                fraccionamiento="00",
                anio="1985",
                suffix="REVISAR",
                pdfs_to_rename=analysis.pdfs_to_rename,
                pdfs_ignored=analysis.pdfs_ignored,
                notes="Prueba unitaria",
            )

            # Verificar que la carpeta física NO se ha tocado
            self.assertTrue(os.path.isdir(folder_path))
            self.assertTrue(os.path.isfile(zero_pdf_1))

            # Aplicar cambios (sin requerir servidor MySQL activo en test unitario aislado)
            ok, msg = store.apply_capture_changes(cid, require_mysql=False)
            self.assertTrue(ok, msg)

            # Verificar que se generaron los hashes SHA-256 y los UUIDs
            applied_files = store.get_files_for_capture(cid)
            target_applied = [f for f in applied_files if f["is_target_zero"] == 1]
            self.assertEqual(len(target_applied), 2)
            self.assertEqual(len(target_applied[0]["file_hash"]), 64)
            self.assertTrue(len(target_applied[0]["file_uuid"]) >= 32)

            new_folder_path = os.path.join(tmp_root, prop_folder)
            self.assertTrue(os.path.isdir(new_folder_path))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        new_folder_path,
                        "01_02_05_01_AUXILIAR_03_00_1985_0001_00.pdf",
                    )
                )
            )
            # El archivo ignorado debe seguir intacto con su nombre original
            self.assertTrue(
                os.path.isfile(
                    os.path.join(new_folder_path, "01_01_01_00_00_00_1991_0001_00.pdf")
                )
            )

            # Ejecutar Rollback y verificar que todo regresa exactamente al original
            rb_ok, rb_msg = store.rollback_capture_changes(cid)
            self.assertTrue(rb_ok, rb_msg)
            self.assertTrue(os.path.isdir(folder_path))
            self.assertTrue(os.path.isfile(zero_pdf_1))
            self.assertTrue(os.path.isfile(zero_pdf_2))
            self.assertTrue(os.path.isfile(non_zero_pdf))

            # Probar exportación e importación JSON en una base de datos limpia
            exported_json = os.path.join(tmp_root, "export_test.json")
            store.export_backup_json(exported_json)
            self.assertTrue(os.path.isfile(exported_json))

            db_file_2 = os.path.join(tmp_root, "test_capturas_2.db")
            store2 = LocalCaptureStore(db_path=db_file_2)
            ins, upd, skp = store2.import_backup_json(exported_json)
            self.assertEqual(ins, 1)
            self.assertEqual(upd, 0)
            self.assertEqual(skp, 0)
            imported_caps = store2.get_all_captures()
            self.assertEqual(len(imported_caps), 1)
            self.assertEqual(
                imported_caps[0]["proposed_folder_name"],
                "01_02_05_01_AUXILIAR_03_00_1985_REVISAR",
            )
            imported_files = store2.get_files_for_capture(imported_caps[0]["id"])
            self.assertEqual(len(imported_files), 3)


if __name__ == "__main__":
    unittest.main()
