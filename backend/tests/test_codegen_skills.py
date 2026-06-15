from app.compiler.codegen import generate_project_files
from app.ir.schemas import EdgeIR, NodeIR, NodeType, SkillConfig, create_default_project


def test_codegen_exports_skills_registry_and_agent_injection():
    project = create_default_project("导出 Skills Agent")
    project.project.id = "skill_codegen_agent"
    project.skills.append(
        SkillConfig(
            id="skill_tone",
            name="语气控制",
            content="请保持礼貌、简洁。",
        )
    )
    project.nodes.extend(
        [
            NodeIR(
                id="agent_1",
                type=NodeType.AGENT,
                label="Agent",
                config={
                    "systemPrompt": "你是客服助手。",
                    "skillIdsJson": '["skill_tone"]',
                    "outputField": "agent_result",
                },
            ),
            NodeIR(
                id="skill_1",
                type=NodeType.SKILL_NODE,
                label="Skill",
                config={"skillId": "skill_tone", "skillName": "语气控制", "outputField": "skill_text"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="agent_1"),
            EdgeIR(id="e2", source="agent_1", target="skill_1"),
        ]
    )

    files = generate_project_files(project)

    assert "src/skill_codegen_agent/skills.py" in files
    assert "skill_tone" in files["src/skill_codegen_agent/skills.py"]
    assert "请保持礼貌" in files["src/skill_codegen_agent/skills.py"]
    nodes_py = files["src/skill_codegen_agent/nodes.py"]
    assert "from .skills import SKILL_REGISTRY" in nodes_py
    assert "_system_with_skills" in nodes_py
    assert "SKILL_REGISTRY.get" in nodes_py
    assert '"skills"' in files["flow/project.graph.json"]
