"""
Pruebas automatizadas del motor de análisis, captura local, aplicación y rollback.
"""

import os
import tempfile
import unittest

import fitz
from src.cover_inserter import get_pdf_page_count, prepend_cover_pages_to_pdfs
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

    def test_cover_inserter_all_single_and_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            cover_path = os.path.join(tmp_root, "caratula.pdf")
            target1_path = os.path.join(tmp_root, "doc1.pdf")
            target2_path = os.path.join(tmp_root, "doc2.pdf")

            # Crear carátula de 3 páginas
            cov_doc = fitz.open()
            for i in range(3):
                p = cov_doc.new_page()
                p.insert_text((50, 50), f"Cover page {i + 1}")
            cov_doc.save(cover_path)
            cov_doc.close()

            # Crear 2 PDFs destino de 2 páginas cada uno
            for p_path in (target1_path, target2_path):
                d = fitz.open()
                for i in range(2):
                    page = d.new_page()
                    page.insert_text((50, 50), f"Content page {i + 1}")
                d.save(p_path)
                d.close()

            # 1. Modo ALL (inserta las 3 páginas al inicio de doc1; excluye cover_path automáticamente)
            ok_cnt, errs, ins_pages = prepend_cover_pages_to_pdfs(
                cover_pdf_path=cover_path,
                target_pdf_paths=[cover_path, target1_path],
                mode="ALL",
            )
            self.assertEqual(ok_cnt, 1)
            self.assertEqual(len(errs), 0)
            self.assertEqual(ins_pages, 3)
            self.assertEqual(get_pdf_page_count(target1_path), 5)
            self.assertEqual(get_pdf_page_count(cover_path), 3)

            # 2. Modo RANGE (páginas 2 a 3 en doc2 -> suma 2 páginas)
            ok_cnt2, errs2, ins_pages2 = prepend_cover_pages_to_pdfs(
                cover_pdf_path=cover_path,
                target_pdf_paths=[target2_path],
                mode="RANGE",
                range_from_1based=2,
                range_to_1based=3,
            )
            self.assertEqual(ok_cnt2, 1)
            self.assertEqual(len(errs2), 0)
            self.assertEqual(ins_pages2, 2)
            self.assertEqual(get_pdf_page_count(target2_path), 4)

    def test_individual_and_bulk_selection_no_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            folder_path = os.path.join(tmp_root, "01_00_00_00_00_00_1990_REVISAR")
            os.makedirs(folder_path)

            # 4 tipos de archivos:
            # 1. Campos en 00 y año 0000
            p1 = os.path.join(folder_path, "01_00_00_00_00_00_0000_0001_00.pdf")
            # 2. Campos en 00 y año 1990
            p2 = os.path.join(folder_path, "01_00_00_00_00_00_1990_0002_00.pdf")
            # 3. Campos con datos y año 0000
            p3 = os.path.join(folder_path, "01_01_02_01_00_00_0000_0003_00.pdf")
            # 4. Campos con datos y año 1988 (preexistente)
            p4 = os.path.join(folder_path, "01_03_04_02_00_00_1988_0004_00.pdf")

            for p in (p1, p2, p3, p4):
                with open(p, "wb") as f:
                    f.write(b"%PDF-1.4 dummy content")

            analysis = scan_directory(folder_path)
            self.assertEqual(len(analysis.all_pdfs), 4)

            # Por defecto, los que tienen campos en 0 o año 0 (p1, p2, p3) están pre-seleccionados:
            self.assertEqual(len(analysis.pdfs_to_rename), 3)
            self.assertEqual(len(analysis.pdfs_ignored), 1)

            # 1. Deseleccionar todos
            analysis.deselect_all()
            self.assertEqual(len(analysis.pdfs_to_rename), 0)
            self.assertEqual(len(analysis.pdfs_ignored), 4)

            # 2. Seleccionar solo los de ceros / año 0
            analysis.select_only_zeros()
            self.assertEqual(len(analysis.pdfs_to_rename), 3)

            # 3. Seleccionar todos (incluyendo el archivo con datos preexistentes para evitar bloqueos)
            analysis.select_all()
            self.assertEqual(len(analysis.pdfs_to_rename), 4)
            self.assertEqual(len(analysis.pdfs_ignored), 0)

            # 4. Generar propuestas con todos seleccionados
            prop_folder, updated = build_proposals(
                analysis,
                delegacion="01",
                seccion="05",
                libro="02",
                tomo="01",
                volumen="00",
                fraccionamiento="00",
                anio="1990",
                suffix="REVISAR",
            )
            self.assertEqual(prop_folder, "01_05_02_01_00_00_1990_REVISAR")
            self.assertEqual(len(updated), 4)

            # Verificar que el PDF preexistente (p4) toma los nuevos campos pero conserva inscripción y bis intactos
            p4_prop = [u for u in updated if u.original_name == "01_03_04_02_00_00_1988_0004_00.pdf"][0]
            self.assertEqual(p4_prop.proposed_name, "01_05_02_01_00_00_1990_0004_00.pdf")

            # 5. Guardar captura y aplicar cambios físicos
            db_file = os.path.join(tmp_root, "test_sel.db")
            store = LocalCaptureStore(db_path=db_file)
            cid = store.save_capture(
                original_folder_path=analysis.folder_path,
                original_folder_name=analysis.folder_name,
                proposed_folder_name=prop_folder,
                delegacion="01",
                seccion="05",
                libro="02",
                tomo="01",
                volumen="00",
                fraccionamiento="00",
                anio="1990",
                suffix="REVISAR",
                pdfs_to_rename=analysis.pdfs_to_rename,
                pdfs_ignored=analysis.pdfs_ignored,
                notes="Prueba seleccion individual y total",
            )

            ok, msg = store.apply_capture_changes(cid, require_mysql=False)
            self.assertTrue(ok, msg)

            new_folder_path = os.path.join(tmp_root, prop_folder)
            self.assertTrue(os.path.isdir(new_folder_path))
            self.assertTrue(os.path.isfile(os.path.join(new_folder_path, "01_05_02_01_00_00_1990_0004_00.pdf")))

            # 6. Rollback
            rb_ok, rb_msg = store.rollback_capture_changes(cid)
            self.assertTrue(rb_ok, rb_msg)
            self.assertTrue(os.path.isfile(p4))


if __name__ == "__main__":
    unittest.main()
